"""
Downloader de páginas web com duas camadas de resiliência:
    1. Playwright (Chromium headless + flags stealth) — executa JavaScript
    2. httpx (fallback HTTP/1.1 ou HTTP/2) — mais rápido, sem JS

Fluxo para cada URL:
    download_url(url) → tenta Playwright → se falhar → tenta httpx → DownloadResult

Por que duas camadas?
    Muitos sites modernos (como portais imobiliários) exigem JavaScript para
    renderizar o conteúdo real. Playwright garante a renderização completa.
    httpx serve como fallback eficiente para sites mais simples.

Proteção anti-bloqueio:
    - Delay aleatório de 1–2s entre requisições (evita rate-limiting)
    - Validação do HTML recebido (rejeita páginas de erro de WAF/Cloudflare)
    - Retry com backoff exponencial via tenacity
"""
from __future__ import annotations

import hashlib
import logging
import random
import time
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

# User-Agent de navegador real para evitar bloqueios simples por header
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
    """Valida se o HTML recebido contém conteúdo real (não é erro de WAF).

    Rejeita páginas de bloqueio (Cloudflare 403, Access Denied) e
    arquivos muito pequenos que indicam resposta vazia.
    """
    if not html or len(html) < 8_000:
        return False

    # Verifica markers de bloqueio no início do HTML
    header_sample = html[:3_000].lower()
    block_markers = [
        "access denied",
        "403 forbidden",
        "enable javascript and cookies to continue",
        "just a moment...",
    ]
    if any(marker in header_sample for marker in block_markers):
        return False

    return True


# ── Camada 1: Playwright (com retry) ─────────────────────────────────────────

@retry(
    retry=retry_if_exception_type(Exception),
    stop=stop_after_attempt(1),     # 1 tentativa — Playwright é lento; httpx retenta
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
                "--disable-blink-features=AutomationControlled",  # flag stealth principal
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

            # Aguarda scripts assíncronos terminarem de carregar
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


# ── Camada 2: httpx (fallback, com retry e backoff) ──────────────────────────

@retry(
    retry=retry_if_exception_type(Exception),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),  # espera 2s, 4s, 8s...
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
        # HTTP/2 é mais eficiente mas nem sempre suportado
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


# ── Orquestrador ──────────────────────────────────────────────────────────────

def download_url(url: str, output_dir: Path) -> DownloadResult:
    """Baixa uma URL, salva o HTML no disco e retorna o resultado.

    Tenta Playwright primeiro (com suporte a JS). Se falhar,
    usa httpx como fallback. Se ambos falharem, retorna ok=False.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / _url_to_filename(url)

    # Tenta Playwright (JavaScript completo + stealth)
    try:
        html = _try_playwright(url)
        filepath.write_text(html, encoding="utf-8")
        size = len(html)
        logger.info("✅ playwright  %s (%d KB)", url, size // 1024)
        return DownloadResult(url=url, filepath=filepath, method="playwright", ok=True, size_bytes=size)
    except Exception as pw_err:
        logger.warning("Playwright falhou: %s — %s", url, pw_err)

    # Tenta httpx (sem JavaScript, mas mais rápido)
    try:
        html = _try_httpx(url)
        filepath.write_text(html, encoding="utf-8")
        size = len(html)
        logger.info("⚠️  httpx       %s (%d KB)", url, size // 1024)
        return DownloadResult(url=url, filepath=filepath, method="httpx", ok=True, size_bytes=size)
    except Exception as httpx_err:
        logger.error("httpx falhou: %s — %s", url, httpx_err)

    err_msg = f"Falha no download: HTML inválido ou bloqueado pelo WAF em {url}"
    logger.error("❌ %s", err_msg)
    return DownloadResult(url=url, filepath=None, method="error", ok=False, error=err_msg)


def download_all(
    urls: list[str],
    output_dir: Path,
    progress_callback: Callable[[int, int, DownloadResult], None] | None = None,
) -> list[DownloadResult]:
    """Baixa todas as URLs sequencialmente com delay anti-rate-limit.

    Args:
        urls:              Lista de URLs para baixar.
        output_dir:        Diretório onde os HTMLs serão salvos.
        progress_callback: Função chamada após cada download (atual, total, resultado).
    """
    results: list[DownloadResult] = []
    total = len(urls)
    logger.info("Iniciando download de %d URL(s) → %s", total, output_dir)

    for i, url in enumerate(urls):
        if i > 0:
            # why: delay aleatório entre requests evita bloqueio por rate-limit
            delay = random.uniform(1.0, 2.0)
            logger.debug("Aguardando %.1fs antes do próximo download...", delay)
            time.sleep(delay)

        result = download_url(url, output_dir)
        results.append(result)

        if progress_callback:
            progress_callback(i + 1, total, result)

    ok_count = sum(1 for r in results if r.ok)
    logger.info("Download concluído: %d/%d com sucesso", ok_count, total)
    return results
