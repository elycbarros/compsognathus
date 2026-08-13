"""
Orquestrador principal: coordena download → parse → export.

Este módulo conecta as três peças do framework:
    downloader.py  →  baixa o HTML de cada URL
    registry.py    →  encontra o plugin correto para o domínio
    record.py      →  recebe os dados estruturados de volta

O resultado final é um DataFrame pandas exportado em Parquet, CSV, JSON, JSONL ou SQLite.
"""
from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import pandas as pd

from compsognathus.core.record import ScrapedRecord
from compsognathus.core.registry import get_parser, get_schema
from compsognathus.downloader import DownloadResult, download_all

# Importa os plugins para que se auto-registrem via @register
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
        return record.model_copy(update={"parse_ok": record.parse_ok and not missing, "parse_errors": errors})
    except Exception as exc:
        logger.error("Erro ao parsear %s: %s", url, exc)
        return ScrapedRecord(
            url=url,
            site=_fallback_site(url),
            parse_ok=False,
            parse_errors=[f"parse: {type(exc).__name__}: {exc}"],
        )


def export_dataframe(df: pd.DataFrame, output_path: Path, fmt: str) -> None:
    """Exporta o DataFrame para o formato especificado.

    Formatos suportados:
        - "parquet" (padrão)
        - "csv"
        - "json"
        - "jsonl"
        - "sqlite" / "db"
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fmt_lower = fmt.lower().strip()

    if fmt_lower == "parquet":
        df.to_parquet(output_path, index=False)
    elif fmt_lower == "csv":
        df.to_csv(output_path, index=False, encoding="utf-8-sig")
    elif fmt_lower == "json":
        df.to_json(output_path, orient="records", indent=2, force_ascii=False)
    elif fmt_lower in ("jsonl", "ndjson"):
        df.to_json(output_path, orient="records", lines=True, force_ascii=False)
    elif fmt_lower in ("sqlite", "db"):
        table_name = "scraped_data"
        with closing(sqlite3.connect(output_path)) as conn:
            df.to_sql(table_name, conn, if_exists="replace", index=False)
    else:
        raise ValueError(f"Formato de exportação não suportado: '{fmt}'. Use: parquet, csv, json, jsonl, sqlite.")


def scrape(
    urls: list[str],
    output_path: Path,
    fmt: str = "parquet",
    html_dir: Path | None = None,
    concurrency: int = 1,
    progress_callback: Callable[[int, int, str], None] | None = None,
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
    if html_dir is None:
        html_dir = output_path.parent / "html"

    # ── ETAPA 1: Download (suporta concorrência) ─────────────────────────────
    logger.info("Etapa 1/3: Baixando %d URL(s) (concorrência=%d)...", len(urls), concurrency)

    def _dl_callback(current: int, total: int, result: DownloadResult) -> None:
        status = "✅" if result.ok else "❌"
        if progress_callback:
            progress_callback(current, total, f"{status} {result.url}")

    download_results = download_all(
        urls, output_dir=html_dir, concurrency=concurrency, progress_callback=_dl_callback
    )

    # ── ETAPA 2: Parse ────────────────────────────────────────────────────────
    logger.info("Etapa 2/3: Parseando HTMLs...")
    records: list[tuple[ScrapedRecord, DownloadResult]] = []

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
        records.append((record, result))

    if not records:
        logger.warning("Nenhum registro extraído. Verifique as URLs e os plugins disponíveis.")
        return pd.DataFrame()

    # ── ETAPA 3: Export ───────────────────────────────────────────────────────
    logger.info("Etapa 3/3: Exportando %d registros → %s (formato: %s)", len(records), output_path, fmt)

    rows = []
    reserved_fields = {"url", "site", "data_coleta", "parse_ok", "parse_errors", "download_ok", "download_method", "download_error"}
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
        }
        conflicting = reserved_fields.intersection(rec.fields)
        if conflicting:
            logger.warning("Campos reservados ignorados no parser %s: %s", rec.site, sorted(conflicting))
        row.update({key: value for key, value in rec.fields.items() if key not in reserved_fields})
        rows.append(row)

    df = pd.DataFrame(rows)
    export_dataframe(df, output_path, fmt=fmt)

    logger.info("✅ Exportado: %s (%d linhas, %d colunas)", output_path, len(df), len(df.columns))
    return df
