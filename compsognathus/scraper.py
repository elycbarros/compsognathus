"""
Orquestrador principal: coordena download → parse → export.

Este módulo conecta as três peças do framework:
    downloader.py  →  baixa o HTML de cada URL
    registry.py    →  encontra o plugin correto para o domínio
    record.py      →  recebe os dados estruturados de volta

O resultado final é um DataFrame pandas exportado em Parquet, CSV, JSON, JSONL
ou SQLite. Quando solicitado, a mesma execução mantém um job retomável e gera
um manifesto ``*.run.json``; esses recursos complementam, mas não alteram, o
fluxo linear de coleta de URLs conhecidas.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import pandas as pd

from compsognathus.core.record import ScrapedRecord
from compsognathus import __version__
from compsognathus.core.registry import get_model, get_parser, get_plugin_info, get_schema
from compsognathus.downloader import DownloadResult, download_all
from compsognathus.jobs import JobStore, unique_urls

# Importa os plugins bundled para que se auto-registrem via @register; plugins
# externos são descobertos pelo registry através de entry points.
import compsognathus.plugins  # noqa: F401

logger = logging.getLogger(__name__)


def _fallback_site(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host or "unknown"


def _is_missing_field(value: object) -> bool:
    """Identifica valores ausentes sem confundir coleções válidas com escalares."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return bool(pd.isna(value)) if pd.api.types.is_scalar(value) else False


def _parse_html_file(filepath: Path, url: str) -> ScrapedRecord:
    """Lê um HTML salvo em disco e converte falhas de parse em registro auditável."""
    try:
        parser_fn = get_parser(url)
    except ValueError as exc:
        logger.warning("Plugin ausente: %s", exc)
        return ScrapedRecord(
            url=url,
            site=_fallback_site(url),
            parse_ok=False,
            parse_errors=[f"plugin: {exc}"],
        )

    try:
        html = filepath.read_text(encoding="utf-8")
        record = parser_fn(html, url)
        schema = get_schema(url)
        missing = [
            field for field in schema
            if field not in record.fields
            or _is_missing_field(record.fields[field])
        ]
        errors = list(dict.fromkeys([*record.parse_errors, *[f"missing: {field}" for field in missing]]))

        model = get_model(url)
        if model is not None:
            try:
                validated = model.model_validate(record.fields)
                fields = {**record.fields, **validated.model_dump()}
                record = record.model_copy(update={"fields": fields})
            except Exception as exc:
                model_errors = getattr(exc, "errors", lambda: [])()
                if model_errors:
                    for detail in model_errors:
                        location = ".".join(str(part) for part in detail.get("loc", ())) or "record"
                        message = detail.get("msg", "valor inválido")
                        errors.append(f"invalid: {location}: {message}")
                else:
                    errors.append(f"invalid: {type(exc).__name__}: {exc}")

        errors = list(dict.fromkeys(errors))
        return record.model_copy(update={"parse_ok": record.parse_ok and not errors, "parse_errors": errors})
    except Exception as exc:
        logger.error("Erro ao parsear %s: %s", url, exc)
        return ScrapedRecord(
            url=url,
            site=_fallback_site(url),
            parse_ok=False,
            parse_errors=[f"parse: {type(exc).__name__}: {exc}"],
        )


def _dataframe_to_markdown(df: pd.DataFrame) -> str:
    """Converte um DataFrame exportado em Markdown estruturado para LLMs / RAG."""
    lines = ["# Compsognathus Dataset Export\n"]
    for idx, row in df.iterrows():
        url = str(row.get("url", f"Item {idx+1}"))
        site = str(row.get("site", "N/A"))
        title = row.get("title") or row.get("name") or url
        lines.append(f"## {title}\n")
        lines.append(f"- **URL**: {url}")
        lines.append(f"- **Site**: {site}")
        if "extracted_at" in row and pd.notna(row["extracted_at"]):
            lines.append(f"- **Extracted At**: {row['extracted_at']}")
        if "parse_ok" in row and pd.notna(row["parse_ok"]):
            lines.append(f"- **Status**: {'OK' if row['parse_ok'] else 'Falha'}")

        lines.append("\n### Dados Extraídos\n")
        skip_cols = {"url", "site", "title", "name", "extracted_at", "parse_ok", "parse_errors"}
        for col in df.columns:
            if col not in skip_cols:
                val = row[col]
                if pd.notna(val):
                    lines.append(f"- **{col}**: {val}")
        lines.append("\n---\n")
    return "\n".join(lines)


def export_dataframe(df: pd.DataFrame, output_path: Path, fmt: str) -> None:
    """Exporta o DataFrame para o formato especificado.

    Formatos suportados:
        - "parquet" (padrão)
        - "csv"
        - "json"
        - "jsonl"
        - "sqlite" / "db"
        - "markdown" / "md"
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fmt_lower = fmt.lower().strip()
    if fmt_lower not in {"parquet", "csv", "json", "jsonl", "ndjson", "sqlite", "db", "markdown", "md"}:
        raise ValueError(f"Formato de exportação não suportado: '{fmt}'. Use: parquet, csv, json, jsonl, sqlite, markdown.")

    # Mantém a extensão final para que pandas escolha o engine correto e só
    # substitui o destino depois que a escrita completa.
    temporary = output_path.with_name(f".{output_path.stem}.tmp{output_path.suffix or '.data'}")
    try:
        if fmt_lower == "parquet":
            df.to_parquet(temporary, index=False)
        elif fmt_lower == "csv":
            df.to_csv(temporary, index=False, encoding="utf-8-sig")
        elif fmt_lower == "json":
            df.to_json(temporary, orient="records", indent=2, force_ascii=False)
        elif fmt_lower in ("jsonl", "ndjson"):
            df.to_json(temporary, orient="records", lines=True, force_ascii=False)
        elif fmt_lower in ("sqlite", "db"):
            with closing(sqlite3.connect(temporary)) as conn:
                df.to_sql("scraped_data", conn, if_exists="replace", index=False)
        elif fmt_lower in ("markdown", "md"):
            md_content = _dataframe_to_markdown(df)
            temporary.write_text(md_content, encoding="utf-8")
        temporary.replace(output_path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_run_manifest(path: Path, manifest: dict) -> None:
    """Escreve o manifesto de forma atômica e sem dados secretos."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.stem}.tmp{path.suffix or '.json'}")
    try:
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _build_run_manifest(
    *,
    urls: list[str],
    records: list[tuple[ScrapedRecord, DownloadResult]],
    started_at: datetime,
    elapsed_seconds: float,
    output_path: Path,
    fmt: str,
    job_dir: Path | None,
    resume: bool,
    cache_html: bool,
    force: bool,
    robots_mode: str,
    concurrency: int,
    domain_concurrency: int,
    domain_delay: float,
) -> dict:
    downloads = [download for _, download in records]
    parse_ok = sum(1 for record, _ in records if record.parse_ok)
    download_ok = sum(1 for download in downloads if download.ok)
    methods = Counter(download.method for download in downloads)
    statuses = Counter(str(download.status_code) for download in downloads if download.status_code is not None)
    errors = Counter(
        error
        for record, download in records
        for error in [*record.parse_errors, *( [download.error_type] if download.error_type else [] )]
        if error
    )
    return {
        "manifest_version": 1,
        "project_version": __version__,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(elapsed_seconds, 6),
        "output": {"path": str(output_path), "format": fmt},
        "configuration": {
            "url_count": len(urls),
            "concurrency": concurrency,
            "domain_concurrency": domain_concurrency,
            "domain_delay": domain_delay,
            "robots_mode": robots_mode,
            "cache_html": cache_html,
            "force": force,
            "resume": resume,
            "job_dir": str(job_dir) if job_dir else None,
        },
        "counts": {
            "records": len(records),
            "parse_ok": parse_ok,
            "parse_failed": len(records) - parse_ok,
            "download_ok": download_ok,
            "download_failed": len(downloads) - download_ok,
            "cache_hits": sum(1 for download in downloads if download.from_cache),
            "robots_denied": sum(1 for download in downloads if download.method == "robots"),
            "retries": sum(max(0, download.attempts - 1) for download in downloads),
            "bytes": sum(download.size_bytes for download in downloads),
        },
        "download_methods": dict(methods),
        "http_statuses": dict(statuses),
        "errors": dict(errors),
        "plugins": list({
            (info["domain"], info["source"], info["version"]): info
            for url in urls
            for info in [get_plugin_info(url)]
            if info is not None
        }.values()),
    }


def scrape(
    urls: list[str],
    output_path: Path,
    fmt: str = "parquet",
    html_dir: Path | None = None,
    concurrency: int = 1,
    progress_callback: Callable[[int, int, str], None] | None = None,
    job_dir: Path | None = None,
    resume: bool = False,
    cache_html: bool = False,
    force: bool = False,
    robots_mode: str = "respect",
    domain_concurrency: int = 1,
    domain_delay: float = 1.0,
    manifest_path: Path | None = None,
) -> pd.DataFrame:
    """Executa o pipeline completo: download → parse → export.

    Args:
        urls:              Lista de URLs para raspar.
        output_path:       Caminho do arquivo de saída.
        fmt:               Formato: "parquet", "csv", "json", "jsonl" ou "sqlite".
        html_dir:          Diretório para salvar HTMLs temporários.
        concurrency:       Número de downloads concorrentes simultâneos.
        progress_callback: Chamada após cada URL (atual, total, status).

    Returns:
        DataFrame com todos os registros coletados.
    """
    started_at = datetime.now(timezone.utc)
    started_clock = time.perf_counter()
    urls = unique_urls(urls)
    if html_dir is None:
        html_dir = output_path.parent / "html"
    store = JobStore(job_dir, urls, resume=resume) if job_dir else None
    cache_enabled = cache_html or store is not None
    effective_force = force or (store is not None and not resume)

    records_by_url: dict[str, tuple[ScrapedRecord, DownloadResult]] = {}
    pending_urls = urls
    if store and resume and not force:
        for url in urls:
            saved = store.load_record(url)
            if saved:
                records_by_url[url] = saved
        pending_urls = [url for url in urls if url not in records_by_url]

    # ── ETAPA 1: Download (suporta concorrência) ─────────────────────────────
    logger.info("Etapa 1/3: Baixando %d URL(s) (concorrência=%d)...", len(pending_urls), concurrency)

    def _dl_callback(current: int, total: int, result: DownloadResult) -> None:
        if store:
            store.save_download(result)
        status = "✅" if result.ok else "❌"
        if progress_callback:
            progress_callback(current, total, f"{status} {result.url}")

    download_kwargs = {
        "domain_concurrency": domain_concurrency,
        "domain_delay": domain_delay,
        "robots_mode": robots_mode,
        "cache_enabled": cache_enabled,
        "force": effective_force,
    }
    try:
        download_results = download_all(
            pending_urls,
            output_dir=html_dir,
            concurrency=concurrency,
            progress_callback=_dl_callback,
            **download_kwargs,
        )
    except TypeError as exc:
        # Mantém compatibilidade com doubles e integrações que implementam a
        # assinatura v1.3/v1.4 de download_all.
        if "unexpected keyword" not in str(exc):
            raise
        download_results = download_all(
            pending_urls,
            output_dir=html_dir,
            concurrency=concurrency,
            progress_callback=_dl_callback,
        )

    # ── ETAPA 2: Parse ────────────────────────────────────────────────────────
    logger.info("Etapa 2/3: Parseando HTMLs...")
    for result in download_results:
        if not result.ok or result.filepath is None:
            logger.warning("Pulando URL com falha no download: %s", result.url)
            record = ScrapedRecord(
                url=result.url,
                site=_fallback_site(result.url),
                parse_ok=False,
                parse_errors=[f"download: {result.error or 'falha desconhecida'}"],
            )
        else:
            record = _parse_html_file(result.filepath, result.url)
        records_by_url[result.url] = (record, result)
        if store:
            store.save_record(record, result)

    records = [records_by_url[url] for url in urls if url in records_by_url]

    if not records:
        logger.warning("Nenhum registro extraído. Verifique as URLs e os plugins disponíveis.")
        manifest = _build_run_manifest(
            urls=urls, records=[], started_at=started_at, elapsed_seconds=time.perf_counter() - started_clock,
            output_path=output_path, fmt=fmt, job_dir=job_dir, resume=resume, cache_html=cache_html,
            force=force, robots_mode=robots_mode, concurrency=concurrency,
            domain_concurrency=domain_concurrency, domain_delay=domain_delay,
        )
        _write_run_manifest(manifest_path or output_path.with_name(f"{output_path.stem}.run.json"), manifest)
        return pd.DataFrame()

    # ── ETAPA 3: Export ───────────────────────────────────────────────────────
    logger.info("Etapa 3/3: Exportando %d registros → %s (formato: %s)", len(records), output_path, fmt)

    rows = []
    reserved_fields = {
        "url", "site", "data_coleta", "parse_ok", "parse_errors", "download_ok",
        "download_method", "download_error", "download_status_code", "download_final_url",
        "download_duration_seconds", "download_attempts", "download_error_type",
        "download_from_cache", "download_retry_after_seconds", "robots_allowed",
    }
    for rec, download in records:
        row = {
            "url": rec.url,
            "site": rec.site,
            "data_coleta": rec.data_coleta,
            "parse_ok": rec.parse_ok,
            "parse_errors": ", ".join(rec.parse_errors),
            "download_ok": download.ok,
            "download_method": download.method,
            "download_error": download.error,
            "download_status_code": getattr(download, "status_code", None),
            "download_final_url": getattr(download, "final_url", None),
            "download_duration_seconds": getattr(download, "duration_seconds", 0.0),
            "download_attempts": getattr(download, "attempts", 0),
            "download_error_type": getattr(download, "error_type", None),
            "download_from_cache": getattr(download, "from_cache", False),
            "download_retry_after_seconds": getattr(download, "retry_after_seconds", None),
            "robots_allowed": getattr(download, "robots_allowed", None),
        }
        conflicting = reserved_fields.intersection(rec.fields)
        if conflicting:
            logger.warning("Campos reservados ignorados no parser %s: %s", rec.site, sorted(conflicting))
        row.update({key: value for key, value in rec.fields.items() if key not in reserved_fields})
        rows.append(row)

    df = pd.DataFrame(rows)
    export_dataframe(df, output_path, fmt=fmt)

    manifest = _build_run_manifest(
        urls=urls, records=records, started_at=started_at, elapsed_seconds=time.perf_counter() - started_clock,
        output_path=output_path, fmt=fmt, job_dir=job_dir, resume=resume, cache_html=cache_html,
        force=force, robots_mode=robots_mode, concurrency=concurrency,
        domain_concurrency=domain_concurrency, domain_delay=domain_delay,
    )
    _write_run_manifest(manifest_path or output_path.with_name(f"{output_path.stem}.run.json"), manifest)

    logger.info("✅ Exportado: %s (%d linhas, %d colunas)", output_path, len(df), len(df.columns))
    return df
