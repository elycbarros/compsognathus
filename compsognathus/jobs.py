"""Estado persistente de coletas, retomada e deduplicação.

O estado é deliberadamente simples: um SQLite por diretório de trabalho,
contendo o último resultado de download e de parse de cada URL.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from compsognathus.core.record import ScrapedRecord
from compsognathus.downloader import DownloadResult


def unique_urls(urls: list[str]) -> list[str]:
    """Remove duplicatas preservando a ordem de entrada."""
    seen: set[str] = set()
    result: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            result.append(url)
    return result


class JobStore:
    """Persistência transacional de uma execução de scraping."""

    def __init__(self, directory: Path, urls: list[str], *, resume: bool = False) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.database = directory / "job.sqlite3"
        self._urls_hash = hashlib.sha256("\n".join(urls).encode()).hexdigest()
        with closing(sqlite3.connect(self.database)) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS job_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS url_state (
                    url TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    download_json TEXT,
                    record_json TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            existing = conn.execute("SELECT value FROM job_meta WHERE key = 'urls_hash'").fetchone()
            if existing and resume and existing[0] != self._urls_hash:
                raise ValueError("As URLs não correspondem ao job existente; use outro --job-dir ou não retome.")
            if not existing or not resume:
                conn.execute("DELETE FROM url_state")
                conn.execute(
                    "INSERT OR REPLACE INTO job_meta(key, value) VALUES ('urls_hash', ?)",
                    (self._urls_hash,),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO job_meta(key, value) VALUES ('created_at', ?)",
                    (datetime.now(timezone.utc).isoformat(),),
                )
            conn.commit()

    def status(self, url: str) -> str | None:
        with closing(sqlite3.connect(self.database)) as conn:
            row = conn.execute("SELECT status FROM url_state WHERE url = ?", (url,)).fetchone()
        return row[0] if row else None

    def save_download(self, result: DownloadResult) -> None:
        payload = asdict(result)
        if payload["filepath"] is not None:
            payload["filepath"] = str(payload["filepath"])
        self._upsert(result.url, "downloaded" if result.ok else "failed", download_json=json.dumps(payload))

    def save_record(self, record: ScrapedRecord, result: DownloadResult) -> None:
        payload = asdict(result)
        if payload["filepath"] is not None:
            payload["filepath"] = str(payload["filepath"])
        self._upsert(
            record.url,
            "parsed",
            download_json=json.dumps(payload),
            record_json=record.model_dump_json(),
        )

    def load_record(self, url: str) -> tuple[ScrapedRecord, DownloadResult] | None:
        with closing(sqlite3.connect(self.database)) as conn:
            row = conn.execute(
                "SELECT download_json, record_json FROM url_state WHERE url = ? AND status = 'parsed'",
                (url,),
            ).fetchone()
        if not row or not row[0] or not row[1]:
            return None
        download = json.loads(row[0])
        if download.get("filepath"):
            download["filepath"] = Path(download["filepath"])
        return ScrapedRecord.model_validate_json(row[1]), DownloadResult(**download)

    def _upsert(
        self,
        url: str,
        status: str,
        *,
        download_json: str | None = None,
        record_json: str | None = None,
    ) -> None:
        with closing(sqlite3.connect(self.database)) as conn:
            conn.execute(
                """
                INSERT INTO url_state(url, status, download_json, record_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    status = excluded.status,
                    download_json = COALESCE(excluded.download_json, url_state.download_json),
                    record_json = COALESCE(excluded.record_json, url_state.record_json),
                    updated_at = excluded.updated_at
                """,
                (url, status, download_json, record_json, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
