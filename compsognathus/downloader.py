"""
Downloader adaptativo de páginas web, subordinado à política do plugin.

O fluxo preserva duas estratégias de transporte:
    - Playwright para páginas que dependem de JavaScript;
    - HTTPX para HTML/JSON estático, com fallback conforme a política escolhida.

O módulo também concentra as garantias operacionais da coleta: retry com
backoff, cache opcional, limites por domínio, robots.txt, metadados de
auditoria e execução concorrente. Ele não descobre links nem transforma a
ferramenta em um crawler genérico.
"""
from __future__ import annotations

import hashlib
import logging
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

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

_STEALTH_HTTP_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Referer": "https://www.google.com/",
}

_STEALTH_JS_INIT = """
// Anti-bot evasion: remove navigator.webdriver
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
});

// Mock plugins and languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['pt-BR', 'pt', 'en-US', 'en'],
});

Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5],
});

// Mock chrome object
window.chrome = window.chrome || {
    runtime: {},
    loadTimes: function() {},
    csi: function() {},
    app: {},
};
"""


@dataclass(frozen=True)
class DownloadPolicy:
    """Política de transporte declarada por um plugin.

    ``browser_first`` mantém o comportamento histórico do projeto. Plugins
    de páginas estáticas podem optar por ``httpx_first`` ou ``httpx_only``.
    Plugins com proteção anti-bot podem optar por ``stealth_browser`` ou ``stealth_http``.
    """

    preferred: Literal[
        "httpx_first", "browser_first", "httpx_only", "browser_only", "stealth_browser", "stealth_http"
    ] = "browser_first"
    timeout_seconds: float = 15.0
    wait_after_load_ms: int = 1_500
    headers: dict[str, str] | None = None
    stealth: bool = False

    def __post_init__(self) -> None:
        if self.preferred not in {
            "httpx_first", "browser_first", "httpx_only", "browser_only", "stealth_browser", "stealth_http"
        }:
            raise ValueError(f"Estratégia de download inválida: {self.preferred!r}")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds deve ser maior que zero")
        if self.wait_after_load_ms < 0:
            raise ValueError("wait_after_load_ms não pode ser negativo")


@dataclass(frozen=True)
class _HttpxClientKey:
    thread_id: int
    http2: bool
    timeout_seconds: float
    headers: tuple[tuple[str, str], ...]


_HTTPX_CLIENTS: dict[_HttpxClientKey, object] = {}
_HTTPX_CLIENTS_LOCK = threading.Lock()
_PLAYWRIGHT_SESSIONS: dict[int, tuple[object, object]] = {}
_PLAYWRIGHT_LOCK = threading.Lock()
_FETCH_METADATA = threading.local()


@dataclass
class DownloadResult:
    """Resultado do download de uma URL."""
    url: str
    filepath: Path | None           # Onde o HTML foi salvo (None se falhou)
    method: str                     # "playwright" | "httpx" | "error"
    ok: bool                        # True se o download foi bem-sucedido
    error: str | None = None        # Mensagem de erro (se ok=False)
    size_bytes: int = 0             # Tamanho do HTML baixado
    status_code: int | None = None
    final_url: str | None = None
    duration_seconds: float = 0.0
    attempts: int = 0
    error_type: str | None = None
    from_cache: bool = False
    retry_after_seconds: float | None = None
    robots_allowed: bool | None = None


def _set_fetch_metadata(
    *,
    status_code: int | None = None,
    final_url: str | None = None,
    retry_after_seconds: float | None = None,
) -> None:
    _FETCH_METADATA.value = {
        "status_code": status_code,
        "final_url": final_url,
        "retry_after_seconds": retry_after_seconds,
    }


def _consume_fetch_metadata() -> dict[str, object]:
    metadata = getattr(_FETCH_METADATA, "value", {})
    _FETCH_METADATA.value = {}
    return metadata


def _retry_after(headers: object) -> float | None:
    """Lê Retry-After em segundos quando o servidor o fornece."""
    try:
        value = headers.get("retry-after") if hasattr(headers, "get") else None
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class DomainRateLimiter:
    """Limita concorrência e espaçamento por hostname, com ajuste simples."""

    def __init__(self, max_concurrency: int = 1, min_delay: float = 1.0) -> None:
        if max_concurrency < 1:
            raise ValueError("domain_concurrency deve ser maior ou igual a 1")
        if min_delay < 0:
            raise ValueError("domain_delay não pode ser negativo")
        self.max_concurrency = max_concurrency
        self.base_delay = min_delay
        self._delays: dict[str, float] = {}
        self._next_allowed: dict[str, float] = {}
        self._semaphores: dict[str, threading.BoundedSemaphore] = {}
        self._lock = threading.Lock()

    def acquire(self, url: str) -> str:
        domain = (urlparse(url).hostname or "").lower()
        with self._lock:
            semaphore = self._semaphores.setdefault(domain, threading.BoundedSemaphore(self.max_concurrency))
        semaphore.acquire()
        with self._lock:
            delay = self._delays.setdefault(domain, self.base_delay)
            wait = max(0.0, self._next_allowed.get(domain, 0.0) - time.monotonic())
            self._next_allowed[domain] = time.monotonic() + wait + delay
        if wait:
            time.sleep(wait)
        return domain

    def release(self, domain: str, result: DownloadResult) -> None:
        with self._lock:
            semaphore = self._semaphores.get(domain)
            delay = self._delays.get(domain, self.base_delay)
            retry_after = getattr(result, "retry_after_seconds", None)
            status_code = getattr(result, "status_code", None)
            if retry_after is not None:
                delay = max(delay, retry_after)
            if not getattr(result, "ok", False) or status_code in {429, 503}:
                delay = min(60.0, max(self.base_delay, delay * 2 or 1.0))
            else:
                delay = max(self.base_delay, delay * 0.8)
            self._delays[domain] = delay
        if semaphore:
            semaphore.release()


class RobotsChecker:
    """Consulta robots.txt uma vez por domínio e conserva o resultado."""

    def __init__(self, mode: Literal["respect", "ignore"] = "respect", timeout: float = 10.0) -> None:
        if mode not in {"respect", "ignore"}:
            raise ValueError("robots_mode deve ser 'respect' ou 'ignore'")
        self.mode = mode
        self.timeout = timeout
        self._parsers: dict[str, RobotFileParser | None] = {}
        self._lock = threading.Lock()

    def check(self, url: str) -> bool:
        if self.mode == "ignore":
            return True
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        with self._lock:
            if domain in self._parsers:
                parser = self._parsers[domain]
            else:
                parser = self._load(parsed.scheme, domain)
                self._parsers[domain] = parser
        if parser is None:
            return True
        return parser.can_fetch(_USER_AGENT, url)

    def _load(self, scheme: str, domain: str) -> RobotFileParser | None:
        import httpx

        try:
            response = httpx.get(
                f"{scheme}://{domain}/robots.txt",
                headers={"User-Agent": _USER_AGENT},
                timeout=self.timeout,
                follow_redirects=True,
            )
            if response.status_code >= 400:
                return None
            parser = RobotFileParser()
            parser.set_url(str(response.url))
            parser.parse(response.text.splitlines())
            return parser
        except Exception as exc:
            logger.warning("Não foi possível consultar robots.txt de %s: %s", domain, exc)
            return None


def _url_to_filename(url: str) -> str:
    """Gera um nome de arquivo único a partir da URL (hash MD5)."""
    return hashlib.md5(url.encode()).hexdigest() + ".html"


def _html_size_bytes(html: str) -> int:
    """Retorna o tamanho real do HTML quando persistido em UTF-8."""
    return len(html.encode("utf-8"))


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


def _policy_headers(policy: DownloadPolicy | None, stealth: bool = False) -> dict[str, str]:
    use_stealth = stealth or (policy is not None and (policy.stealth or policy.preferred in ("stealth_browser", "stealth_http")))
    base = _STEALTH_HTTP_HEADERS if use_stealth else _HTTPX_HEADERS
    headers = dict(base)
    if policy and policy.headers:
        headers.update(policy.headers)
    return headers


def _get_httpx_client(policy: DownloadPolicy | None, http2: bool, stealth: bool = False):
    """Obtém um cliente HTTP reutilizável por thread e configuração."""
    import httpx

    timeout_seconds = policy.timeout_seconds if policy else 15.0
    headers = _policy_headers(policy, stealth=stealth)
    key = _HttpxClientKey(
        thread_id=threading.get_ident(),
        http2=http2,
        timeout_seconds=timeout_seconds,
        headers=tuple(sorted(headers.items())),
    )
    with _HTTPX_CLIENTS_LOCK:
        client = _HTTPX_CLIENTS.get(key)
        if client is None:
            timeout = httpx.Timeout(
                connect=min(5.0, timeout_seconds),
                read=timeout_seconds,
                write=min(5.0, timeout_seconds),
                pool=min(5.0, timeout_seconds),
            )
            client = httpx.Client(
                headers=headers,
                timeout=timeout,
                follow_redirects=True,
                http2=http2,
            )
            _HTTPX_CLIENTS[key] = client
        return client


def _close_httpx_clients() -> None:
    with _HTTPX_CLIENTS_LOCK:
        clients = list(_HTTPX_CLIENTS.values())
        _HTTPX_CLIENTS.clear()
    for client in clients:
        close = getattr(client, "close", None)
        if close:
            close()


def _get_playwright_browser():
    from playwright.sync_api import sync_playwright

    thread_id = threading.get_ident()
    with _PLAYWRIGHT_LOCK:
        session = _PLAYWRIGHT_SESSIONS.get(thread_id)
        if session:
            return session[1]
        runtime = sync_playwright().start()
        browser = runtime.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-infobars",
                "--ignore-certificate-errors",
            ],
        )
        _PLAYWRIGHT_SESSIONS[thread_id] = (runtime, browser)
        return browser


def _close_playwright_sessions() -> None:
    with _PLAYWRIGHT_LOCK:
        sessions = list(_PLAYWRIGHT_SESSIONS.values())
        _PLAYWRIGHT_SESSIONS.clear()
    for runtime, browser in sessions:
        close = getattr(browser, "close", None)
        if close:
            close()
        stop = getattr(runtime, "stop", None)
        if stop:
            stop()


# ── Transporte Playwright (com retry) ────────────────────────────────────────

@retry(
    retry=retry_if_exception_type(Exception),
    stop=stop_after_attempt(2),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _try_playwright(
    url: str,
    policy: DownloadPolicy | None = None,
    *,
    reuse: bool = False,
    stealth: bool = False,
) -> str:
    """Abre a URL com Chromium headless e flags stealth. Retorna o HTML renderizado."""
    from playwright.sync_api import TimeoutError as PWTimeout

    logger.debug("Playwright: abrindo %s", url)
    timeout_ms = int((policy.timeout_seconds if policy else 15.0) * 1000)
    wait_ms = policy.wait_after_load_ms if policy else 1_500
    use_stealth = stealth or (policy is not None and (policy.stealth or policy.preferred == "stealth_browser"))

    if reuse:
        browser = _get_playwright_browser()
        context = browser.new_context(
            user_agent=_USER_AGENT,
            viewport={"width": 1920, "height": 1080},
            locale="pt-BR",
        )
        try:
            page = context.new_page()
            if use_stealth:
                page.add_init_script(_STEALTH_JS_INIT)
            page.set_default_navigation_timeout(timeout_ms)
            if policy and policy.headers:
                page.set_extra_http_headers(policy.headers)
            response = page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            page.wait_for_timeout(wait_ms)
            html = page.content()
            _set_fetch_metadata(
                status_code=getattr(response, "status", None),
                final_url=getattr(page, "url", url),
                retry_after_seconds=_retry_after(getattr(response, "headers", {})),
            )
            if not _is_valid_html(html):
                raise ValueError("HTML inválido ou bloqueado por WAF")
            return html
        except PWTimeout as exc:
            logger.warning("Playwright: timeout em %s — %s", url, exc)
            raise
        finally:
            context.close()

    from playwright.sync_api import sync_playwright
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
            if use_stealth:
                page.add_init_script(_STEALTH_JS_INIT)
            page.set_default_navigation_timeout(timeout_ms)
            if policy and policy.headers:
                page.set_extra_http_headers(policy.headers)
            response = page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            page.wait_for_timeout(wait_ms)
            html = page.content()
            _set_fetch_metadata(
                status_code=getattr(response, "status", None),
                final_url=getattr(page, "url", url),
                retry_after_seconds=_retry_after(getattr(response, "headers", {})),
            )
            if not _is_valid_html(html):
                raise ValueError("HTML inválido ou bloqueado por WAF")
            logger.debug("Playwright: OK (%d KB) — %s", _html_size_bytes(html) // 1024, url)
            return html
        except PWTimeout as exc:
            logger.warning("Playwright: timeout em %s — %s", url, exc)
            raise
        finally:
            browser.close()


# ── Transporte HTTPX / Stealth HTTP (com fallback conforme a política) ───────

@retry(
    retry=retry_if_exception_type(Exception),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _try_httpx(
    url: str,
    policy: DownloadPolicy | None = None,
    *,
    reuse: bool = False,
    stealth: bool = False,
) -> str:
    """Fallback HTTP — tenta HTTP/2 primeiro, depois HTTP/1.1."""
    import httpx

    use_stealth = stealth or (policy is not None and (policy.stealth or policy.preferred == "stealth_http"))
    logger.debug("httpx: baixando %s (stealth=%s)", url, use_stealth)
    timeout_seconds = policy.timeout_seconds if policy else 15.0
    headers = _policy_headers(policy, stealth=use_stealth)

    # Tentativa opcional via curl_cffi para TLS fingerprint impersonation real
    if use_stealth:
        try:
            from curl_cffi import requests as cffi_requests
            cffi_resp = cffi_requests.get(
                url,
                headers=headers,
                timeout=timeout_seconds,
                impersonate="chrome120",
            )
            _set_fetch_metadata(
                status_code=getattr(cffi_resp, "status_code", None),
                final_url=str(getattr(cffi_resp, "url", url)),
                retry_after_seconds=_retry_after(getattr(cffi_resp, "headers", {})),
            )
            cffi_resp.raise_for_status()
            html = cffi_resp.text
            if not _is_valid_html(html):
                raise ValueError("HTML inválido ou bloqueado por WAF")
            logger.debug("curl_cffi/stealth: OK (%d KB) — %s", _html_size_bytes(html) // 1024, url)
            return html
        except ImportError:
            pass
        except Exception as exc:
            logger.debug("curl_cffi falhou (%s), tentando fallback com httpx...", exc)

    timeout = httpx.Timeout(
        connect=min(5.0, timeout_seconds),
        read=timeout_seconds,
        write=min(5.0, timeout_seconds),
        pool=min(5.0, timeout_seconds),
    )

    html = None
    try:
        if reuse:
            client = _get_httpx_client(policy, http2=True, stealth=use_stealth)
            response = client.get(url)
            _set_fetch_metadata(
                status_code=getattr(response, "status_code", None),
                final_url=str(getattr(response, "url", url)),
                retry_after_seconds=_retry_after(getattr(response, "headers", {})),
            )
            response.raise_for_status()
            html = response.text
        else:
            with httpx.Client(headers=headers, timeout=timeout, follow_redirects=True, http2=True) as client:
                response = client.get(url)
                _set_fetch_metadata(
                    status_code=getattr(response, "status_code", None),
                    final_url=str(getattr(response, "url", url)),
                    retry_after_seconds=_retry_after(getattr(response, "headers", {})),
                )
                response.raise_for_status()
                html = response.text

    except Exception as exc:
        logger.debug("httpx h2 falhou (%s), tentando HTTP/1.1...", exc)
        if reuse:
            client = _get_httpx_client(policy, http2=False, stealth=use_stealth)
            response = client.get(url)
            _set_fetch_metadata(
                status_code=getattr(response, "status_code", None),
                final_url=str(getattr(response, "url", url)),
                retry_after_seconds=_retry_after(getattr(response, "headers", {})),
            )
            response.raise_for_status()
            html = response.text
        else:
            with httpx.Client(headers=headers, timeout=timeout, follow_redirects=True, http2=False) as client:
                response = client.get(url)
                _set_fetch_metadata(
                    status_code=getattr(response, "status_code", None),
                    final_url=str(getattr(response, "url", url)),
                    retry_after_seconds=_retry_after(getattr(response, "headers", {})),
                )
                response.raise_for_status()
                html = response.text

    _set_fetch_metadata(
        status_code=getattr(response, "status_code", None),
        final_url=str(getattr(response, "url", url)),
        retry_after_seconds=_retry_after(getattr(response, "headers", {})),
    )

    if not _is_valid_html(html):
        raise ValueError("HTML inválido ou bloqueado por WAF")

    logger.debug("httpx: OK (%d KB) — %s", _html_size_bytes(html) // 1024, url)
    return html


# ── Orquestrador de Download ──────────────────────────────────────────────────

def download_url(
    url: str,
    output_dir: Path,
    policy: DownloadPolicy | None = None,
    *,
    reuse_resources: bool = False,
    cache_enabled: bool = False,
    force: bool = False,
) -> DownloadResult:
    """Baixa uma URL, salva o HTML e retorna evidências da operação."""
    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / _url_to_filename(url)
    started = time.perf_counter()

    if cache_enabled and filepath.exists() and not force:
        try:
            html = filepath.read_text(encoding="utf-8")
            if _is_valid_html(html):
                return DownloadResult(
                    url=url,
                    filepath=filepath,
                    method="cache",
                    ok=True,
                    size_bytes=_html_size_bytes(html),
                    final_url=url,
                    duration_seconds=time.perf_counter() - started,
                    from_cache=True,
                )
        except (OSError, UnicodeError) as exc:
            logger.debug("Cache inválido para %s: %s", url, exc)

    preferred = policy.preferred if policy else "browser_first"
    methods = {
        "browser_first": ("playwright", "httpx"),
        "httpx_first": ("httpx", "playwright"),
        "httpx_only": ("httpx",),
        "browser_only": ("playwright",),
        "stealth_browser": ("stealth_browser", "httpx"),
        "stealth_http": ("stealth_http", "playwright"),
    }[preferred]

    def _fetch(method: str) -> str:
        if method in ("playwright", "stealth_browser"):
            is_stealth = (method == "stealth_browser") or (policy is not None and policy.stealth)
            fn = _try_playwright
            if policy is None and not reuse_resources and not is_stealth:
                try:
                    return fn(url)
                except TypeError:
                    pass
            try:
                return fn(url, policy, reuse=reuse_resources, stealth=is_stealth)
            except TypeError as exc:
                if "stealth" in str(exc) or "unexpected keyword" in str(exc) or "positional argument" in str(exc):
                    if policy is None and not reuse_resources:
                        return fn(url)
                    return fn(url, policy, reuse=reuse_resources)
                raise
        elif method in ("httpx", "stealth_http"):
            is_stealth = (method == "stealth_http") or (policy is not None and policy.stealth)
            fn = _try_httpx
            if policy is None and not reuse_resources and not is_stealth:
                try:
                    return fn(url)
                except TypeError:
                    pass
            try:
                return fn(url, policy, reuse=reuse_resources, stealth=is_stealth)
            except TypeError as exc:
                if "stealth" in str(exc) or "unexpected keyword" in str(exc) or "positional argument" in str(exc):
                    if policy is None and not reuse_resources:
                        return fn(url)
                    return fn(url, policy, reuse=reuse_resources)
                raise
        raise ValueError(f"Método de download desconhecido: {method}")

    errors: dict[str, Exception] = {}
    failure_metadata: dict[str, object] = {}
    attempts = 0
    for method in methods:
        attempts += 1
        try:
            _consume_fetch_metadata()
            html = _fetch(method)
            metadata = _consume_fetch_metadata()
            filepath.write_text(html, encoding="utf-8")
            size = _html_size_bytes(html)
            elapsed = time.perf_counter() - started
            logger.info("✅ %-10s %s (%d KB)", method, url, size // 1024)
            return DownloadResult(
                url=url,
                filepath=filepath,
                method=method,
                ok=True,
                size_bytes=size,
                status_code=metadata.get("status_code"),
                final_url=metadata.get("final_url") or url,
                duration_seconds=elapsed,
                attempts=attempts,
                retry_after_seconds=metadata.get("retry_after_seconds"),
            )
        except Exception as exc:
            failure_metadata = _consume_fetch_metadata()
            errors[method] = exc
            if method == "playwright":
                logger.warning("Playwright falhou: %s — %s", url, exc)
            else:
                logger.error("httpx falhou: %s — %s", url, exc)

    error_parts = [
        f"{method}={type(error).__name__}: {error}"
        for method, error in errors.items()
    ]
    err_msg = f"Falha no download em {url}: " + "; ".join(error_parts)
    logger.error("❌ %s", err_msg)
    last_error = next(reversed(errors.values()))
    return DownloadResult(
        url=url,
        filepath=None,
        method="error",
        ok=False,
        error=err_msg,
        duration_seconds=time.perf_counter() - started,
        attempts=attempts,
        error_type=type(last_error).__name__,
        status_code=failure_metadata.get("status_code"),
        final_url=failure_metadata.get("final_url") or url,
        retry_after_seconds=failure_metadata.get("retry_after_seconds"),
    )


def download_all(
    urls: list[str],
    output_dir: Path,
    concurrency: int = 1,
    progress_callback: Callable[[int, int, DownloadResult], None] | None = None,
    policy_resolver: Callable[[str], DownloadPolicy | None] | None = None,
    domain_concurrency: int = 1,
    domain_delay: float = 1.0,
    robots_mode: Literal["respect", "ignore"] = "ignore",
    cache_enabled: bool = False,
    force: bool = False,
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
    output_dir.mkdir(parents=True, exist_ok=True)
    limiter = DomainRateLimiter(domain_concurrency, domain_delay)
    robots = RobotsChecker(robots_mode)

    total = len(urls)
    logger.info("Iniciando download de %d URL(s) → %s (threads=%d)", total, output_dir, concurrency)

    if policy_resolver is None:
        def policy_resolver(url: str) -> DownloadPolicy | None:
            try:
                from compsognathus.core.registry import get_download_policy
                return get_download_policy(url)
            except ValueError:
                return None

    if concurrency <= 1 or total <= 1:
        # Execução sequencial
        results: list[DownloadResult] = []
        try:
            for i, url in enumerate(urls):
                if i > 0:
                    time.sleep(random.uniform(1.0, 2.0))
                domain = limiter.acquire(url)
                res = DownloadResult(url=url, filepath=None, method="error", ok=False)
                try:
                    if not robots.check(url):
                        res = DownloadResult(
                            url=url,
                            filepath=None,
                            method="robots",
                            ok=False,
                            error="robots.txt disallow",
                            final_url=url,
                            error_type="RobotsDenied",
                            robots_allowed=False,
                        )
                    else:
                        try:
                            res = download_url(
                                url,
                                output_dir,
                                policy_resolver(url),
                                reuse_resources=True,
                                cache_enabled=cache_enabled,
                                force=force,
                            )
                        except TypeError as exc:
                            if "unexpected keyword" in str(exc) or "positional argument" in str(exc):
                                res = download_url(url, output_dir)
                            else:
                                raise
                        res.robots_allowed = True
                finally:
                    limiter.release(domain, res)
                results.append(res)
                if progress_callback:
                    progress_callback(i + 1, total, res)
            return results
        finally:
            _close_httpx_clients()
            _close_playwright_sessions()

    # Execução concorrente via ThreadPoolExecutor
    results: list[DownloadResult | None] = [None] * total
    completed_count = 0

    def _worker(url_item: str) -> DownloadResult:
        # Pequeno jitter para evitar rajada idêntica no mesmo milissegundo
        time.sleep(random.uniform(0.1, 0.5))
        domain = limiter.acquire(url_item)
        try:
            if not robots.check(url_item):
                return DownloadResult(
                    url=url_item,
                    filepath=None,
                    method="robots",
                    ok=False,
                    error="robots.txt disallow",
                    final_url=url_item,
                    error_type="RobotsDenied",
                    robots_allowed=False,
                )
            policy = policy_resolver(url_item)
            try:
                result = download_url(
                    url_item,
                    output_dir,
                    policy,
                    reuse_resources=True,
                    cache_enabled=cache_enabled,
                    force=force,
                )
            except TypeError as exc:
                # Compatibilidade com doubles antigos que aceitam apenas dois args.
                if "unexpected keyword" in str(exc) or "positional argument" in str(exc):
                    result = download_url(url_item, output_dir)
                else:
                    raise
            result.robots_allowed = True
            return result
        finally:
            # O resultado é observado no loop principal; a liberação aqui
            # mantém o semáforo seguro mesmo em exceções inesperadas.
            limiter.release(domain, locals().get("result", DownloadResult(url_item, None, "error", False)))

    try:
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
                    res = DownloadResult(
                        url=url,
                        filepath=None,
                        method="error",
                        ok=False,
                        error=str(exc),
                        final_url=url,
                        error_type=type(exc).__name__,
                    )

                results[index] = res
                completed_count += 1

                if progress_callback:
                    progress_callback(completed_count, total, res)
    finally:
        _close_httpx_clients()
        _close_playwright_sessions()

    # Garante a ordem original das URLs na lista final
    return [result for result in results if result is not None]
