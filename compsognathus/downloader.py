"""
Downloader de páginas web com duas camadas de resiliência e suporte a concorrência:
    1. Playwright (Chromium headless + flags stealth) — executa JavaScript
    2. httpx (fallback HTTP/1.1 ou HTTP/2) — mais rápido, sem JS

Fluxo para cada URL:
    download_url(url) → tenta Playwright → se falhar → tenta httpx → DownloadResult

Proteção anti-bloqueio:
    - Delay aleatório entre requisições
    - Validação do HTML recebido (rejeita páginas de erro de WAF/Cloudflare)
    - Retry com backoff exponencial via tenacity
    - Execução concorrente via ThreadPoolExecutor
"""
from __future__ import annotations

import hashlib
import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_HTTPX_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.google.com/",
}


@dataclass
class DownloadResult:
    """Resultado do download de uma URL."""
    url: str
    filepath: Path | None           # Onde o HTML foi salvo (None se falhou)
    method: str                     # "playwright" | "httpx" | "error"
    ok: bool                        # True se o download foi bem-sucedido
    error: str | None = None        # Mensagem de erro (se ok=False)
    size_bytes: int = 0             # Tamanho do HTML baixado


def _url_to_filename(url: str) -> str:
    """Gera um nome de arquivo único a partir da URL (hash MD5)."""
    return hashlib.md5(url.encode()).hexdigest() + ".html"


def _is_valid_html(html: str) -> bool:
    """Valida se o HTML recebido contém conteúdo real (não é erro de WAF)."""
    if not html or len(html.strip()) < 512:
        return False

    header_sample = html[:3_000].lower()
    if "<html" not in header_sample and "<!doctype html" not in header_sample:
        return False

    block_markers = [
        "access denied",
        "403 forbidden",
        "enable javascript and cookies to continue",
        "just a moment...",
        "cf-chl-",
    ]
    if any(marker in header_sample for marker in block_markers):
        return False

    return True


# ── Camada 1: Playwright (com retry) ─────────────────────────────────────────

@retry(
    retry=retry_if_exception_type(Exception),
    stop=stop_after_attempt(2),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _try_playwright(url: str) -> str:
    """Abre a URL com Chromium headless e flags stealth. Retorna o HTML renderizado."""
    from playwright.sync_api import TimeoutError as PWTimeout
    from playwright.sync_api import sync_playwright

    logger.debug("Playwright: abrindo %s", url)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-infobars",
                "--ignore-certificate-errors",
            ],
        )
        try:
            context = browser.new_context(
                user_agent=_USER_AGENT,
                viewport={"width": 1920, "height": 1080},
                locale="pt-BR",
            )
            page = context.new_page()
            page.set_default_navigation_timeout(15_000)
            page.goto(url, timeout=15_000, wait_until="domcontentloaded")

            page.wait_for_timeout(1_500)
            html = page.content()

            if not _is_valid_html(html):
                raise ValueError("HTML inválido ou bloqueado por WAF")

            logger.debug("Playwright: OK (%d KB) — %s", len(html) // 1024, url)
            return html
        except PWTimeout as exc:
            logger.warning("Playwright: timeout em %s — %s", url, exc)
            raise
        finally:
            browser.close()


# ── Camada 2: httpx (fallback) ───────────────────────────────────────────────

@retry(
    retry=retry_if_exception_type(Exception),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _try_httpx(url: str) -> str:
    """Fallback HTTP — tenta HTTP/2 primeiro, depois HTTP/1.1."""
    import httpx

    logger.debug("httpx: baixando %s", url)
    timeout = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)

    html = None
    try:
        with httpx.Client(headers=_HTTPX_HEADERS, timeout=timeout, follow_redirects=True, http2=True) as client:
            response = client.get(url)
            response.raise_for_status()
            html = response.text
    except Exception as exc:
        logger.debug("httpx h2 falhou (%s), tentando HTTP/1.1...", exc)
        with httpx.Client(headers=_HTTPX_HEADERS, timeout=timeout, follow_redirects=True, http2=False) as client:
            response = client.get(url)
            response.raise_for_status()
            html = response.text

    if not _is_valid_html(html):
        raise ValueError("HTML inválido ou bloqueado por WAF")

    logger.debug("httpx: OK (%d KB) — %s", len(html) // 1024, url)
    return html


# ── Orquestrador de Download ──────────────────────────────────────────────────

def download_url(url: str, output_dir: Path) -> DownloadResult:
    """Baixa uma URL, salva o HTML no disco e retorna o resultado."""
    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / _url_to_filename(url)
    pw_error: Exception | None = None
    httpx_error: Exception | None = None

    try:
        html = _try_playwright(url)
        filepath.write_text(html, encoding="utf-8")
        size = len(html)
        logger.info("✅ playwright  %s (%d KB)", url, size // 1024)
        return DownloadResult(url=url, filepath=filepath, method="playwright", ok=True, size_bytes=size)
    except Exception as exc:
        pw_error = exc
        logger.warning("Playwright falhou: %s — %s", url, exc)

    try:
        html = _try_httpx(url)
        filepath.write_text(html, encoding="utf-8")
        size = len(html)
        logger.info("⚠️  httpx       %s (%d KB)", url, size // 1024)
        return DownloadResult(url=url, filepath=filepath, method="httpx", ok=True, size_bytes=size)
    except Exception as exc:
        httpx_error = exc
        logger.error("httpx falhou: %s — %s", url, exc)

    err_msg = (
        f"Falha no download em {url}: "
        f"Playwright={type(pw_error).__name__}: {pw_error}; "
        f"httpx={type(httpx_error).__name__}: {httpx_error}"
    )
    logger.error("❌ %s", err_msg)
    return DownloadResult(url=url, filepath=None, method="error", ok=False, error=err_msg)


def download_all(
    urls: list[str],
    output_dir: Path,
    concurrency: int = 1,
    progress_callback: Callable[[int, int, DownloadResult], None] | None = None,
) -> list[DownloadResult]:
    """Baixa todas as URLs com suporte a execução concorrente.

    Args:
        urls:              Lista de URLs para baixar.
        output_dir:        Diretório onde os HTMLs serão salvos.
        concurrency:       Número de threads simultâneas para download (default=1).
        progress_callback: Função chamada após cada download (atual, total, resultado).
    """
    if concurrency < 1:
        raise ValueError("concurrency deve ser maior ou igual a 1")

    total = len(urls)
    logger.info("Iniciando download de %d URL(s) → %s (threads=%d)", total, output_dir, concurrency)

    if concurrency <= 1 or total <= 1:
        # Execução sequencial
        results: list[DownloadResult] = []
        for i, url in enumerate(urls):
            if i > 0:
                time.sleep(random.uniform(1.0, 2.0))
            res = download_url(url, output_dir)
            results.append(res)
            if progress_callback:
                progress_callback(i + 1, total, res)
        return results

    # Execução concorrente via ThreadPoolExecutor
    results: list[DownloadResult | None] = [None] * total
    completed_count = 0

    def _worker(url_item: str) -> DownloadResult:
        # Pequeno jitter para evitar rajada idêntica no mesmo milissegundo
        time.sleep(random.uniform(0.1, 0.5))
        return download_url(url_item, output_dir)

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        future_to_index = {
            executor.submit(_worker, url): index for index, url in enumerate(urls)
        }

        for future in as_completed(future_to_index):
            index = future_to_index[future]
            url = urls[index]
            try:
                res = future.result()
            except Exception as exc:
                res = DownloadResult(url=url, filepath=None, method="error", ok=False, error=str(exc))

            results[index] = res
            completed_count += 1

            if progress_callback:
                progress_callback(completed_count, total, res)

    # Garante a ordem original das URLs na lista final
    return [result for result in results if result is not None]
