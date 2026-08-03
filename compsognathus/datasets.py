"""Funções compartilhadas para ler e interpretar datasets exportados.

Manter esta lógica fora da CLI deixa os comandos ``report`` e ``validate``
pequenos e garante que ambos aceitem exatamente os mesmos formatos.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pandas as pd


def load_dataframe(file: Path) -> pd.DataFrame:
    """Carrega CSV, JSON, JSONL, Parquet ou SQLite gerado pelo Compsognathus."""
    if not file.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {file}")

    suffix = file.suffix.lower()
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(file)
    if suffix == ".csv":
        return pd.read_csv(file)
    if suffix in {".json", ".jsonl", ".ndjson"}:
        return pd.read_json(file, lines=suffix in {".jsonl", ".ndjson"})
    if suffix in {".db", ".sqlite", ".sqlite3"}:
        with closing(sqlite3.connect(file)) as conn:
            return pd.read_sql_query("SELECT * FROM scraped_data", conn)

    # Parquet é a saída padrão; a mensagem do pandas ajuda a diagnosticar
    # extensões não suportadas ou arquivos corrompidos.
    return pd.read_parquet(file)


def quality_bool_series(df: pd.DataFrame, column: str, default: bool) -> pd.Series:
    """Normaliza uma coluna booleana exportada em CSV, JSON ou Parquet."""
    if column not in df.columns:
        return pd.Series(default, index=df.index, dtype=bool)

    values = df[column]
    if values.dtype == bool:
        return values.fillna(False)
    return values.astype(str).str.strip().str.lower().isin({"true", "1", "yes", "sim"})
