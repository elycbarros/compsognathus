"""Testes do carregador compartilhado entre report e validate."""
from pathlib import Path

import pandas as pd

from compsognathus.datasets import load_dataframe, quality_bool_series


def test_load_dataframe_le_jsonl(tmp_path: Path):
    file = tmp_path / "dados.ndjson"
    file.write_text('{"parse_ok": true}\n{"parse_ok": false}\n', encoding="utf-8")

    df = load_dataframe(file)

    assert len(df) == 2
    assert df["parse_ok"].tolist() == [True, False]


def test_quality_bool_series_normaliza_strings():
    df = pd.DataFrame({"parse_ok": ["sim", "false", "1", None]})

    assert quality_bool_series(df, "parse_ok", True).tolist() == [True, False, True, False]
