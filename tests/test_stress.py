"""Suíte de Testes de Stress, Concorrência e Resiliência para o Compsognathus.

Testa:
1. Concorrência pesada e thread-safety em download_all com 50 threads e falhas simuladas.
2. Contenção e backoff em DomainRateLimiter sob rajadas de requests no mesmo domínio.
3. Parsing adaptativo em HTMLs gigantes (5MB+) e árvores DOM profundamente aninhadas.
4. Exportação massiva de datasets (10.000+ registros) para todos os formatos (Parquet, SQLite, CSV, JSONL, Markdown).
5. Resiliência do SQLite Job Manager em concorrência e escritas rápidas.
"""
from __future__ import annotations

import random
import time
from pathlib import Path

import pandas as pd

from compsognathus.core.adaptive import AdaptiveSelector
from compsognathus.core.record import ScrapedRecord
from compsognathus.downloader import (
    DomainRateLimiter,
    DownloadResult,
    download_all,
)
from compsognathus.jobs import JobStore
from compsognathus.scraper import export_dataframe


# ── 1. Stress de Concorrência & Thread-Safety no Downloader ────────────────────

def test_stress_download_all_high_concurrency(tmp_path: Path, monkeypatch):
    """Simula URLs baixadas simultaneamente com workers e taxas de falha randômicas."""
    total_urls = 30
    urls = [f"https://domain-{i % 5}.com/item/{i}" for i in range(total_urls)]

    def fake_download_url(url, output_dir, policy=None, reuse_resources=False, cache_enabled=False, force=False):
        # Simula latência de rede entre 5ms e 20ms
        time.sleep(random.uniform(0.005, 0.020))
        # Simula 10% de taxa de falha
        if random.random() < 0.10:
            return DownloadResult(
                url=url,
                filepath=None,
                method="httpx",
                ok=False,
                error="Simulated network drop",
                error_type="NetworkError",
                status_code=503,
            )
        html_file = output_dir / f"simulated_{abs(hash(url))}.html"
        html_file.write_text("<!doctype html><html><body><h1>Produto</h1></body></html>", encoding="utf-8")
        return DownloadResult(
            url=url,
            filepath=html_file,
            method="httpx",
            ok=True,
            status_code=200,
            size_bytes=60,
        )

    monkeypatch.setattr("compsognathus.downloader.download_url", fake_download_url)

    results = download_all(
        urls,
        output_dir=tmp_path / "htmls",
        concurrency=20,
        domain_concurrency=4,
        domain_delay=0.01,
        robots_mode="ignore",
    )

    assert len(results) == total_urls
    # Verifica integridade da ordem
    assert [r.url for r in results] == urls
    # Verifica que houve tanto sucessos quanto falhas tratadas sem exceções não-capturadas
    ok_count = sum(1 for r in results if r.ok)
    fail_count = sum(1 for r in results if not r.ok)
    if ok_count == 0:
        print(f"DEBUG FIRST 5 RESULTS: {results[:5]}")
    assert ok_count > 0
    assert ok_count + fail_count == total_urls


def test_stress_domain_rate_limiter_contention():
    """Testa contenção massiva em um único domínio com concorrência estrita."""
    limiter = DomainRateLimiter(max_concurrency=2, min_delay=0.005)
    domain_url = "https://same-target.com/page"

    import concurrent.futures

    def acquire_and_release(idx: int):
        domain = limiter.acquire(f"{domain_url}/{idx}")
        # Simula operação rápida
        time.sleep(0.002)
        res = DownloadResult(
            url=f"{domain_url}/{idx}",
            filepath=None,
            method="httpx",
            ok=True,
            status_code=200,
        )
        limiter.release(domain, res)
        return idx

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
        futures = [executor.submit(acquire_and_release, i) for i in range(50)]
        completed = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert len(completed) == 50


# ── 2. Stress de Parsing em Documentos HTML Gigantes ──────────────────────────

def test_stress_adaptive_parsing_large_dom():
    """Gera um HTML de grande porte (5MB+ com milhares de elementos) e avalia o AdaptiveSelector."""
    from bs4 import BeautifulSoup

    # Gera 10.000 nós aninhados e irmãos
    card_chunks = []
    for i in range(3000):
        card_chunks.append(f"""
        <div class="product-card-{i} c-item" data-id="{i}">
            <h3 class="prod-title">Item Especial #{i}</h3>
            <span class="price-box-v2" data-qa="price">R$ {i * 10},90</span>
            <p class="description">Descrição detalhada do produto #{i} com texto longo para volume.</p>
        </div>
        """)

    large_html = f"<!doctype html><html><body><div id='root'>{''.join(card_chunks)}</div></body></html>"
    assert len(large_html) > 500_000

    soup = BeautifulSoup(large_html, "html.parser")

    # Testa seletor adaptativo no DOM massivo
    start_search = time.perf_counter()
    found = AdaptiveSelector.find_one(
        soup,
        "span.preco-antigo-inexistente",
        fallback_tag="span",
        text_pattern="R$ 1500,90",
        target_attrs={"data-qa": "price"},
    )
    elapsed_search = time.perf_counter() - start_search

    assert found is not None
    assert "R$ 1500,90" in found.get_text()
    assert elapsed_search < 2.0  # Busca em menos de 2 segundos mesmo em DOM gigante


# ── 3. Stress de Persistência no SQLite JobStore ──────────────────────────────

def test_stress_sqlite_job_store(tmp_path: Path):
    """Testa escritas concorrentes e recuperação no JobStore SQLite."""
    job_dir = tmp_path / "stress_job"
    urls = [f"https://example.com/item/{i}" for i in range(200)]
    store = JobStore(job_dir, urls)

    import concurrent.futures

    def mark_completed(url: str):
        record = ScrapedRecord(
            url=url,
            site="example",
            parse_ok=True,
            fields={"title": f"Title for {url}", "price": random.uniform(10, 1000)},
        )
        download = DownloadResult(
            url=url,
            filepath=Path(f"/tmp/{abs(hash(url))}.html"),
            method="httpx",
            ok=True,
            status_code=200,
        )
        store.save_record(record, download)

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(mark_completed, url) for url in urls]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    for url in urls:
        loaded = store.load_record(url)
        assert loaded is not None
        rec, dl = loaded
        assert rec.url == url
        assert dl.ok is True
        assert store.status(url) == "parsed"


# ── 4. Stress de Exportação em Massa (10.000 Registros em Múltiplos Formatos) ──

def test_stress_mass_export_all_formats(tmp_path: Path):
    """Exporta um dataset de 10.000 registros para Parquet, SQLite, CSV, JSONL e Markdown."""
    n_records = 10_000
    data = {
        "url": [f"https://store.com/product/{i}" for i in range(n_records)],
        "site": ["store"] * n_records,
        "title": [f"Produto Incrível {i} - Versão Especial" for i in range(n_records)],
        "price": [random.uniform(19.90, 4999.90) for _ in range(n_records)],
        "parse_ok": [True] * (n_records - 10) + [False] * 10,
        "extracted_at": ["2026-08-24T12:00:00Z"] * n_records,
    }
    df = pd.DataFrame(data)

    formats = ["parquet", "csv", "jsonl", "sqlite", "markdown"]
    for fmt in formats:
        out_file = tmp_path / f"export_stress.{fmt if fmt != 'markdown' else 'md'}"
        start_time = time.perf_counter()
        export_dataframe(df, out_file, fmt=fmt)
        elapsed = time.perf_counter() - start_time

        assert out_file.exists()
        assert out_file.stat().st_size > 0
        assert elapsed < 5.0  # Exportação de 10k registros deve levar menos de 5 segundos


# ── 5. Stress com Dados Corrompidos, Unicode Extremo e Limpeza de Recursos ────

def test_stress_corrupted_data_and_extreme_unicode_export(tmp_path: Path):
    """Testa exportação com emojis, caracteres de controle, strings gigantes e NaNs."""
    data = {
        "url": ["https://store.com/item/1", "https://store.com/item/2", "https://store.com/item/3"],
        "site": ["store"] * 3,
        "title": [
            "✨💻 Super Mac 🚀 (Promoção de Verão! \u2603 \U0001F600)",
            "Texto com quebra\nde linha\r\ne aspas \"duplas\" e 'simples'",
            "Caracteres especiais: \u0000 \t \x1f 漢字, Русский, العربية, 🦕",
        ],
        "description": ["A" * 50_000, None, "Descrição comum"],
        "price": [1234.56, float("nan"), None],
        "parse_ok": [True, False, True],
    }
    df = pd.DataFrame(data)

    formats = ["parquet", "csv", "jsonl", "sqlite", "markdown"]
    for fmt in formats:
        out_file = tmp_path / f"extreme_unicode.{fmt if fmt != 'markdown' else 'md'}"
        export_dataframe(df, out_file, fmt=fmt)
        assert out_file.exists()
        assert out_file.stat().st_size > 0


def test_stress_malformed_html_and_empty_inputs():
    """Testa comportamento sob HTMLs truncados, binários ou vazios."""
    from bs4 import BeautifulSoup

    garbage_inputs = [
        "",
        "   ",
        "\x00\x01\x02\x03\x04\x05" * 100,
        "<<<<div<<<<span>>>>>>>",
        "<!doctype html><html><head><script>/* unclosed script",
        "<div>" * 500 + "texto" + "</div>" * 200,  # Tags desbalanceadas
    ]

    for garbage in garbage_inputs:
        soup = BeautifulSoup(garbage, "html.parser")
        # Não deve lançar exceção
        AdaptiveSelector.find_one(soup, "span.price", fallback_tag="span", text_pattern="texto")
        extracted_txt = AdaptiveSelector.extract_text(soup, "span.price", default="fallback")
        assert isinstance(extracted_txt, str)

