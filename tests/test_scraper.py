"""Testes do pipeline com downloads simulados e sem acesso à rede."""

import math
from pathlib import Path

from compsognathus.core.record import ScrapedRecord
from compsognathus.core.registry import register
from compsognathus.downloader import DownloadResult
from compsognathus.scraper import scrape


def test_scrape_preserva_falha_de_download_e_metadados(tmp_path, monkeypatch):
    fixture = Path(__file__).parent / "fixtures" / "books_toscrape_sample.html"
    downloaded = tmp_path / "book.html"
    downloaded.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
    urls = [
        "https://books.toscrape.com/catalogue/book/index.html",
        "https://books.toscrape.com/catalogue/falha/index.html",
    ]

    def fake_download_all(urls, output_dir, concurrency, progress_callback):
        results = [
            DownloadResult(url=urls[0], filepath=downloaded, method="httpx", ok=True),
            DownloadResult(url=urls[1], filepath=None, method="error", ok=False, error="timeout"),
        ]
        for index, result in enumerate(results, 1):
            progress_callback(index, len(results), result)
        return results

    monkeypatch.setattr("compsognathus.scraper.download_all", fake_download_all)
    df = scrape(urls, tmp_path / "out.csv", fmt="csv")

    assert len(df) == 2
    assert bool(df.iloc[0]["parse_ok"])
    assert bool(df.iloc[0]["download_ok"])
    assert bool(df.iloc[1]["parse_ok"]) is False
    assert df.iloc[1]["download_error"] == "timeout"
    assert "download: timeout" in df.iloc[1]["parse_errors"]


def test_scrape_aplica_schema_e_protege_metadados(tmp_path, monkeypatch):
    @register("quality-test.com", schema=["titulo"])
    def parse_quality(html, url):
        return ScrapedRecord(
            url=url,
            site="quality",
            fields={"url": "url-falsa", "titulo": None},
        )

    html_file = tmp_path / "quality.html"
    html_file.write_text("<html><body>ok</body></html>", encoding="utf-8")
    url = "https://quality-test.com/item"
    monkeypatch.setattr(
        "compsognathus.scraper.download_all",
        lambda urls, output_dir, concurrency, progress_callback: [
            DownloadResult(url=url, filepath=html_file, method="httpx", ok=True)
        ],
    )

    df = scrape([url], tmp_path / "out.json", fmt="json")
    assert df.iloc[0]["url"] == url
    assert bool(df.iloc[0]["parse_ok"]) is False
    assert "missing: titulo" in df.iloc[0]["parse_errors"]


def test_scrape_considera_nan_como_campo_ausente(tmp_path, monkeypatch):
    @register("nan-quality-test.com", schema=["preco"])
    def parse_quality(html, url):
        return ScrapedRecord(url=url, site="quality", fields={"preco": math.nan})

    html_file = tmp_path / "quality.html"
    html_file.write_text("<html><body>ok</body></html>", encoding="utf-8")
    url = "https://nan-quality-test.com/item"
    monkeypatch.setattr(
        "compsognathus.scraper.download_all",
        lambda urls, output_dir, concurrency, progress_callback: [
            DownloadResult(url=url, filepath=html_file, method="httpx", ok=True)
        ],
    )

    df = scrape([url], tmp_path / "out.json", fmt="json")

    assert bool(df.iloc[0]["parse_ok"]) is False
    assert "missing: preco" in df.iloc[0]["parse_errors"]
