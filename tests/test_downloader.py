"""Testes das validações locais do downloader, sem acesso à rede."""

import sys
from types import ModuleType, SimpleNamespace
from pathlib import Path

import pytest

from compsognathus.downloader import (
    _is_valid_html,
    _try_httpx,
    _try_playwright,
    _url_to_filename,
    download_all,
    download_url,
)


VALID_HTML = "<!doctype html><html><body>" + ("conteudo " * 70) + "</body></html>"


def test_html_pequeno_mas_completo_e_valido():
    assert len(VALID_HTML) < 8_000
    assert _is_valid_html(VALID_HTML) is True


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


def test_nome_de_arquivo_e_deterministico_e_unico():
    first = _url_to_filename("https://example.com/item/1")
    repeated = _url_to_filename("https://example.com/item/1")
    other = _url_to_filename("https://example.com/item/2")

    assert first == repeated
    assert first != other
    assert first.endswith(".html")


def test_download_url_salva_resultado_playwright(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("compsognathus.downloader._try_playwright", lambda url: VALID_HTML)
    monkeypatch.setattr(
        "compsognathus.downloader._try_httpx",
        lambda url: (_ for _ in ()).throw(AssertionError("fallback não deveria executar")),
    )

    result = download_url("https://example.com/item", tmp_path)

    assert result.ok is True
    assert result.method == "playwright"
    assert result.filepath.read_text(encoding="utf-8") == VALID_HTML
    assert result.size_bytes == len(VALID_HTML)


def test_download_url_mede_tamanho_real_em_bytes_utf8(tmp_path: Path, monkeypatch):
    html = VALID_HTML.replace("conteudo", "conteúdo")
    monkeypatch.setattr("compsognathus.downloader._try_playwright", lambda url: html)
    monkeypatch.setattr(
        "compsognathus.downloader._try_httpx",
        lambda url: (_ for _ in ()).throw(AssertionError("fallback não deveria executar")),
    )

    result = download_url("https://example.com/item-unicode", tmp_path)

    assert result.size_bytes == len(html.encode("utf-8"))
    assert result.size_bytes > len(html)


def test_download_url_usa_httpx_como_fallback(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "compsognathus.downloader._try_playwright",
        lambda url: (_ for _ in ()).throw(RuntimeError("chromium indisponível")),
    )
    monkeypatch.setattr("compsognathus.downloader._try_httpx", lambda url: VALID_HTML)

    result = download_url("https://example.com/item", tmp_path)

    assert result.ok is True
    assert result.method == "httpx"
    assert result.filepath.exists()


def test_download_all_sequencial_notifica_progresso(tmp_path: Path, monkeypatch):
    urls = ["https://example.com/1", "https://example.com/2"]
    progress = []

    monkeypatch.setattr("compsognathus.downloader.time.sleep", lambda seconds: None)
    monkeypatch.setattr(
        "compsognathus.downloader.download_url",
        lambda url, output_dir: SimpleNamespace(url=url, ok=True),
    )

    results = download_all(
        urls,
        output_dir=tmp_path,
        progress_callback=lambda current, total, result: progress.append((current, total, result.url)),
    )

    assert [result.url for result in results] == urls
    assert progress == [(1, 2, urls[0]), (2, 2, urls[1])]


def test_download_all_concorrente_preserva_ordem_e_converte_excecao(tmp_path: Path, monkeypatch):
    urls = ["https://example.com/1", "https://example.com/2"]

    monkeypatch.setattr("compsognathus.downloader.time.sleep", lambda seconds: None)

    def fake_download(url, output_dir):
        if url.endswith("/2"):
            raise RuntimeError("falha inesperada do worker")
        return SimpleNamespace(url=url, ok=True)

    monkeypatch.setattr("compsognathus.downloader.download_url", fake_download)

    results = download_all(urls, output_dir=tmp_path, concurrency=2)

    assert [result.url for result in results] == urls
    assert results[0].ok is True
    assert results[1].ok is False
    assert "worker" in results[1].error


def test_try_httpx_prioriza_http2(monkeypatch):
    protocols = []

    class FakeResponse:
        text = VALID_HTML

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, **kwargs):
            protocols.append(kwargs["http2"])

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url):
            return FakeResponse()

    fake_httpx = SimpleNamespace(Timeout=lambda **kwargs: object(), Client=FakeClient)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)

    assert _try_httpx("https://example.com/item") == VALID_HTML
    assert protocols == [True]


def test_try_playwright_fecha_browser(monkeypatch):
    state = {"closed": False, "goto": None}

    class FakePage:
        def set_default_navigation_timeout(self, timeout):
            state["timeout"] = timeout

        def goto(self, url, **kwargs):
            state["goto"] = url

        def wait_for_timeout(self, timeout):
            state["wait"] = timeout

        def content(self):
            return VALID_HTML

    class FakeBrowser:
        def new_context(self, **kwargs):
            return SimpleNamespace(new_page=lambda: FakePage())

        def close(self):
            state["closed"] = True

    browser = FakeBrowser()
    runtime = SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kwargs: browser))

    class FakePlaywright:
        def __enter__(self):
            return runtime

        def __exit__(self, *args):
            return None

    fake_sync_api = ModuleType("playwright.sync_api")
    fake_sync_api.TimeoutError = TimeoutError
    fake_sync_api.sync_playwright = FakePlaywright
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)

    assert _try_playwright("https://example.com/item") == VALID_HTML
    assert state["goto"] == "https://example.com/item"
    assert state["closed"] is True
